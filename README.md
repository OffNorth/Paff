# 🤖 Solana Memecoin X2/X3 Call Bot — V1

Bot Telegram de **détection précoce** de memecoins Solana présentant plusieurs
signaux mesurables simultanés (momentum prix, volume, buyers/sellers, holder
growth, liquidité, activité X/Twitter).

> ⚠️ **Le bot ne prédit rien.** Il calcule un score de probabilité/qualité de
> setup basé uniquement sur des données mesurables et publiques. Aucun score,
> aussi élevé soit-il, ne garantit un mouvement de prix. Ceci n'est **pas**
> un conseil financier. Utilise-le comme un outil de surveillance, pas comme
> un système de décision automatique.

## Ce que fait la V1

- Découverte de nouveaux tokens Solana via DexScreener (paires pump.fun/pumpswap + tokens boostés)
- Récupération des données market temps réel (prix, volume, liquidité, buyers/sellers, market cap)
- Score total 0-100 configurable (`config.json`), calculé sur : momentum prix, volume, buyers/sellers,
  holder growth, liquidité, activité wallet, momentum social
- Risk engine : score de risque 0-100 + flags (faible liquidité, token trop récent, volume suspect, etc.)
- Alertes Telegram par paliers (🟡 WATCH / 🟢 POTENTIAL / 🔥 STRONG) avec boutons (Chart, DexScreener,
  Pump.fun, Solscan, Copy Mint)
- Anti-spam avec cooldown configurable, mais nouvelle alerte autorisée si le score progresse fortement
- Tracking automatique de chaque call en base SQLite (temps pour atteindre x2/x3/x5/x10, ATH)
- Backtest : statistiques agrégées (`/stats` dans Telegram) — % de calls ayant atteint chaque palier,
  temps moyen, multiple moyen/médian
- Volet X/Twitter **optionnel et désactivé par défaut** (interface `TwitterTracker` interchangeable) :
  sans configuration, le bot fonctionne à 100% sur les données market seules, avec un score social à 0

Le volet Birdeye (holders réels) est optionnel : sans clé API, le bot utilise un proxy basé sur le
flux net d'acheteurs pour estimer la croissance des holders.

## Architecture

```
memecoin-call-bot/
├── bot/            telegram.py, alerts.py
├── scanners/       dexscreener.py, birdeye.py, pumpfun.py, market.py
├── social/         twitter_tracker.py, twitter_parser.py, x_scraper.py, social_score.py
├── scoring/        momentum.py, risk.py, score.py
├── database/       models.py, database.py
├── backtest/       tracker.py, report.py
├── config.json     poids du score, seuils d'alerte, flags de risque
├── tracked_accounts.json   comptes X suivis (optionnel)
├── .env.example
├── requirements.txt
└── main.py
```

---

## Installation — Windows

1. **Installer Python 3.11+** : https://www.python.org/downloads/ (cocher "Add Python to PATH" à l'installation)

2. **Ouvrir PowerShell** dans le dossier du projet, puis :

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

3. **Configurer le bot Telegram** :
   - Crée un bot via [@BotFather](https://t.me/BotFather) sur Telegram → récupère le `TELEGRAM_BOT_TOKEN`
   - Récupère ton `TELEGRAM_CHAT_ID` (envoie un message à ton bot puis va sur
     `https://api.telegram.org/bot<TON_TOKEN>/getUpdates` pour voir le `chat.id`)
   - Copie `.env.example` en `.env` :
     ```powershell
     copy .env.example .env
     ```
   - Ouvre `.env` et remplis `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`

4. **Lancer le bot** :

```powershell
python main.py
```

Le bot tourne tant que la fenêtre PowerShell reste ouverte. Pour l'arrêter : `Ctrl+C`.

---

## Installation — Termux (Android)

1. **Installer Termux** depuis F-Droid (recommandé, la version Play Store est obsolète) :
   https://f-droid.org/packages/com.termux/

2. **Préparer l'environnement** :

```bash
pkg update && pkg upgrade -y
pkg install python git -y
```

3. **Récupérer le projet** (transfère le dossier sur le téléphone, ou via `git clone` si tu le
   mets sur un repo, puis) :

```bash
cd memecoin-call-bot
pip install -r requirements.txt
```

Si l'installation de certains paquets échoue (compilation native), installe d'abord les
outils de build :
```bash
pkg install build-essential libffi openssl -y
```

4. **Configurer** :

```bash
cp .env.example .env
nano .env   # remplis TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID, Ctrl+X puis Y pour sauver
```

5. **Lancer** :

```bash
python main.py
```

6. **Garder le bot actif en arrière-plan** sur Termux :

```bash
pkg install tmux -y
tmux new -s memebot
python main.py
# Détacher la session sans arrêter le bot : Ctrl+B puis D
# Pour revenir : tmux attach -t memebot
```

Pense aussi à désactiver l'optimisation de batterie pour Termux (Paramètres Android) et à
garder `termux-wake-lock` actif si tu veux que ça tourne longtemps en tâche de fond :
```bash
termux-wake-lock
```

---

## Configuration

Tout se règle dans **`config.json`** (poids du score, seuils d'alerte, cooldown, flags de risque)
et **`tracked_accounts.json`** (comptes X suivis avec leur poids, optionnel).

## Activer le volet X/Twitter (optionnel)

Par défaut, `main.py` utilise `NullTracker` (aucune donnée X, score social toujours à 0). Pour
activer le tracking X via `twscrape` :

1. Ajoute un compte X dont tu possèdes les identifiants/cookies :
   ```bash
   twscrape add_cookie mon_compte "auth_token=...; ct0=..."
   ```
2. Dans `main.py`, remplace :
   ```python
   self.social_tracker = NullTracker()
   ```
   par :
   ```python
   from social.x_scraper import XScraperTracker
   self.social_tracker = XScraperTracker(accounts_db=os.getenv("TWSCRAPE_DB", "x_accounts.db"))
   ```

⚠️ N'utilise que des comptes/cookies t'appartenant. Aucune protection ni limitation d'un
service tiers n'est contournée par ce projet.

## Commandes Telegram

- `/start` — présentation
- `/status` — état du scanner
- `/stats` — statistiques de backtest (% de calls ayant atteint x2/x3/x5/x10, temps moyen, multiple moyen)
- `/config` — seuils et poids actuels

## Phase 2 — implémentée

Toutes les fonctionnalités ci-dessous existent dans le code et sont **désactivées par défaut**
dans `config.json` (le bot reste identique à la V1 tant que tu ne les actives pas explicitement).

### 1. Suivi de wallets performants (`scanners/wallet_tracker.py`)

Remplace le proxy `wallet_activity_score` par un vrai signal : détecte si des wallets Solana que
**tu** juges performants ont une transaction récente touchant le token, via le RPC public Solana.

Activation :
1. Remplis `tracked_wallets.json` avec les adresses des wallets à suivre (poids configurable)
2. Dans `config.json` : `"wallet_tracking": {"enabled": true}`
3. (optionnel) Mets un RPC dédié dans `.env` (`SOLANA_RPC_URL`) — le RPC public est rate-limité

### 2. Comparaison avec les tokens historiques gagnants (`backtest/pattern_compare.py`)

Calcule une similarité 0-100 entre le profil marché du token évalué (âge, ratio volume/liquidité,
ratio buyers/sellers, market cap d'entrée) et les tokens qui ont historiquement atteint x3+ dans
ta base de calls. Reste à 0 tant qu'il y a moins de 10 calls fermés en historique — pas de
signal fantôme sur une base vide. Actif par défaut (`pattern_compare.enabled: true`), s'affiche
dans l'alerte Telegram dès qu'il y a assez d'historique.

### 3. Dashboard web (`web/dashboard.py`)

Page HTML légère (aiohttp, Chart.js en CDN, aucune dépendance supplémentaire) : KPIs globaux,
% de réussite par tranche de market cap, par heure UTC, comptes X les plus actifs, historique
des calls récents.

Activation : `"dashboard": {"enabled": true, "port": 8080}` dans `config.json`, puis ouvre
`http://127.0.0.1:8080` (ou l'IP de la machine sur le réseau local) une fois le bot lancé.

### 4. Statistiques détaillées (`backtest/report.py`)

En plus de `/stats` (Telegram, vue d'ensemble), le dashboard expose : réussite par tranche de
market cap, par heure de la journée, et volume de mentions par compte X suivi.

### 5. Machine learning (`ml/train.py`, `ml/predict.py`)

⚠️ **Désactivé par défaut, volontairement.** Conformément au principe "pas de ML pour faire
joli", le modèle ne s'entraîne que si tu as accumulé au moins **200 calls fermés** avec features
enregistrées :

```bash
python -m ml.train
```

Si tu n'as pas encore assez de données, la commande te dit combien il en manque et ne crée rien.
Une fois `ml/model.json` généré, active `"ml": {"enabled": true}` dans `config.json` : la
probabilité de succès (x2+) prédite par le modèle s'ajoute comme signal informatif dans l'alerte
Telegram (`🎲 Modèle ML`) — elle n'influence jamais le score total ni la décision d'alerter.
Le modèle est une régression logistique simple, implémentée sans dépendance externe (pas de
scikit-learn/numpy requis).

## Avertissement

Ce projet est un outil de surveillance basé sur des données publiques mesurables. Les memecoins
sont des actifs extrêmement volatils et risqués. Aucun score produit par ce bot ne constitue un
conseil financier ni une garantie de performance, passée ou future.
