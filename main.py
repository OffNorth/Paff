"""
Solana Memecoin X2/X3 Call Bot — point d'entrée.

⚠️ Ce bot ne prédit rien. Il calcule un score de probabilité/qualité de
setup à partir de données mesurables (prix, volume, buyers/sellers,
holders, liquidité, activité X). Aucun score, aussi élevé soit-il, ne
garantit un mouvement de prix. Ceci n'est pas un conseil financier.
"""
import asyncio
import json
import logging
import os
from dotenv import load_dotenv
import aiohttp

from database.database import Database
from scanners.dexscreener import DexScreenerScanner
from scanners.birdeye import BirdeyeScanner
from scanners.market import MarketAggregator
from scanners.pumpfun import discover_pumpfun_tokens, discover_boosted_tokens
from social.twitter_tracker import NullTracker
from social.social_score import SocialScorer
from social.twitter_parser import matches_token
from scoring.score import TokenScorer, level_for_score
from scoring.risk import RiskEngine
from backtest.tracker import CallTracker
from backtest.report import compute_stats
from backtest.pattern_compare import PatternComparator, extract_entry_features
from scanners.wallet_tracker import WalletTracker, NullWalletTracker
from ml.predict import MLPredictor
from bot.telegram import TelegramBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")


def load_config() -> dict:
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_tracked_accounts() -> dict:
    path = "tracked_accounts.json"
    if not os.path.exists(path):
        return {"accounts": [], "keywords": [], "min_followers": 0}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_tracked_wallets(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [w for w in data.get("wallets", []) if w.get("address") and not w["address"].startswith("REPLACE_WITH")]


class Scanner:
    def __init__(self, config: dict):
        self.config = config
        self.db = Database("memecoin_bot.db")
        self.session: aiohttp.ClientSession | None = None
        self.social_tracker = NullTracker()  # remplace par XScraperTracker si twscrape est configuré
        self.social_scorer = SocialScorer(config)
        self.token_scorer = TokenScorer(config["score_weights"])
        self.risk_engine = RiskEngine(config["risk_flags"])
        self.tg: TelegramBot | None = None
        self.call_tracker: CallTracker | None = None
        self.wallet_tracker = None
        self.pattern_comparator: PatternComparator | None = None
        self.ml_predictor: MLPredictor | None = None
        self._seen_recently: set[str] = set()

    async def setup(self):
        await self.db.connect()
        self.session = aiohttp.ClientSession()
        dex = DexScreenerScanner(self.session)
        birdeye = BirdeyeScanner(self.session, os.getenv("BIRDEYE_API_KEY") or None)
        self.market = MarketAggregator(dex, birdeye)
        self.dex = dex
        self.call_tracker = CallTracker(self.db, self.market, self.config)

        # Phase 2 : wallet tracking
        wt_cfg = self.config.get("wallet_tracking", {})
        if wt_cfg.get("enabled"):
            wallets = load_tracked_wallets(wt_cfg.get("accounts_file", "tracked_wallets.json"))
            rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
            self.wallet_tracker = WalletTracker(self.session, rpc_url, wallets) if wallets else NullWalletTracker()
        else:
            self.wallet_tracker = NullWalletTracker()

        # Phase 2 : comparaison de patterns historiques
        self.pattern_comparator = PatternComparator(self.db)

        # Phase 2 : modèle ML (informatif uniquement, jamais bloquant), actif seulement
        # si config["ml"]["enabled"] ET si ml/model.json existe (entraîné via python -m ml.train)
        if self.config.get("ml", {}).get("enabled"):
            self.ml_predictor = MLPredictor(self.config.get("ml", {}).get("model_path", "ml/model.json"))
        else:
            self.ml_predictor = MLPredictor(model_path="__disabled__")

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID doivent être définis dans .env")
        self.tg = TelegramBot(token, chat_id, self.config, stats_provider=self._stats_provider)
        self.tg.build_app()

    async def _stats_provider(self) -> dict:
        return await compute_stats(self.db, self.config.get("backtest", {}).get("targets"))

    async def discover(self) -> list[str]:
        pumpfun = await discover_pumpfun_tokens(self.dex, limit=20)
        boosted = await discover_boosted_tokens(self.dex, limit=20)
        mints = list(dict.fromkeys(pumpfun + boosted))
        return mints

    async def evaluate_token(self, mint: str):
        market = await self.market.fetch(mint)
        if not market or not market.get("mint"):
            return
        if market.get("liquidity_usd", 0) < self.config["min_liquidity_usd"]:
            return

        await self.db.upsert_token(market)
        await self.db.add_price_snapshot(market)

        mentions = await self.social_tracker.search_token_mentions(market.get("symbol") or "")
        mentions = [m for m in mentions if matches_token(m.get("content", ""), market.get("symbol"), mint)]
        social = self.social_scorer.compute(mentions)
        triggering_accounts = sorted({m.get("account") for m in mentions if m.get("account")})

        # Phase 2 : enrichit le dict market avec le signal wallets performants avant le scoring
        wallet_info = await self.wallet_tracker.early_buyers_for(mint)
        market.update(wallet_info)
        for label in wallet_info.get("smart_wallets_buying", []):
            await self.db.log_wallet_buy(label, "", mint)

        scores = self.token_scorer.score(market, social)
        risk = self.risk_engine.assess(market)

        total = scores["total"]
        if total < self.config["min_total_score"]:
            return

        level = level_for_score(total, self.config["alert_thresholds"])
        if not level:
            return

        if not await self._should_alert(mint, total):
            return

        age_minutes = self._age_minutes(market.get("pair_created_at"))
        entry_features = extract_entry_features(market, age_minutes)

        # Phase 2 : signaux d'appoint informatifs, jamais utilisés pour bloquer une alerte
        pc_cfg = self.config.get("pattern_compare", {})
        pattern_similarity = None
        if pc_cfg.get("enabled"):
            pattern_similarity = await self.pattern_comparator.similarity_score(
                entry_features, min_multiple=pc_cfg.get("min_multiple", 3.0)
            )
        ml_proba = self.ml_predictor.predict_proba(entry_features) if self.ml_predictor.available else None

        alert = {
            **market,
            **scores,
            "total_score": total,
            "risk_score": risk["risk_score"],
            "risk_flags": risk["risk_flags"],
            "level": level,
            "age_minutes": age_minutes,
            "pattern_similarity": pattern_similarity,
            "ml_success_probability": round(ml_proba * 100, 1) if ml_proba is not None else None,
        }
        await self.tg.send_alert(alert)
        await self.db.record_alert(alert)
        await self.call_tracker.register_call(alert, entry_features=entry_features, triggering_accounts=triggering_accounts)
        logger.info(f"Alerte envoyée: ${market.get('symbol')} score={total} level={level}")

    async def _should_alert(self, mint: str, total_score: float) -> bool:
        last = await self.db.last_alert_for_mint(mint)
        if not last:
            return True
        cooldown = self.config["alert_cooldown_seconds"]
        import datetime
        last_sent = datetime.datetime.fromisoformat(last["sent_at"])
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - last_sent).total_seconds()
        if elapsed < cooldown:
            # Autorise quand même une alerte si le score a fortement progressé
            delta = self.config.get("rescan_score_delta_for_new_alert", 8)
            return total_score - (last["total_score"] or 0) >= delta
        return True

    def _age_minutes(self, created_ms):
        if not created_ms:
            return None
        import time
        return (time.time() * 1000 - created_ms) / 60000

    async def scan_loop(self):
        interval = self.config["scan_interval_seconds"]
        while True:
            try:
                mints = await self.discover()
                logger.info(f"Scan: {len(mints)} tokens candidats")
                for mint in mints:
                    await self.evaluate_token(mint)
            except Exception as e:
                logger.error(f"Erreur pendant le scan: {e}")
            await asyncio.sleep(interval)

    async def call_tracking_loop(self):
        interval = self.config.get("backtest", {}).get("snapshot_interval_seconds", 60)
        while True:
            try:
                await self.call_tracker.update_all()
            except Exception as e:
                logger.error(f"Erreur pendant le suivi des calls: {e}")
            await asyncio.sleep(interval)

    async def run(self):
        await self.setup()
        async with self.tg.app:
            await self.tg.app.start()
            await self.tg.app.updater.start_polling()
            logger.info("🤖 Bot démarré. Scanner actif.")
            tasks = [self.scan_loop(), self.call_tracking_loop()]
            if self.config.get("dashboard", {}).get("enabled"):
                from web.dashboard import run_dashboard
                tasks.append(run_dashboard(self.db, self.config))
            try:
                await asyncio.gather(*tasks)
            finally:
                await self.tg.app.updater.stop()
                await self.tg.app.stop()
                await self.session.close()
                await self.db.close()


async def main():
    load_dotenv()
    config = load_config()
    scanner = Scanner(config)
    await scanner.run()


if __name__ == "__main__":
    asyncio.run(main())
