# Scrapper ENT CESI

Script d'extraction de l'emploi du temps depuis l'ENT CESI avec export en format ICS.

## Installation & Utilisation

### Option 1 : Avec Docker (recommandé)

#### 1. Créer un fichier `.env` avec vos identifiants

Copier `.env.example` en `.env` :

```bash
cp .env.example .env
```

Puis remplir le fichier `.env` avec vos identifiants CESI :

```
IDENTIFIANT=votre.email@viacesi.fr
MOT_DE_PASSE=votre_mot_de_passe
```

#### 2. Lancer avec docker-compose

```bash
docker-compose up --build
```

Le fichier `emploi_du_temps.ics` sera généré dans le répertoire courant.

#### Alternative avec docker run

```bash
docker build -t scrapper-ent .
docker run --rm \
  -e IDENTIFIANT="votre.email@viacesi.fr" \
  -e MOT_DE_PASSE="votre_mot_de_passe" \
  -v $(pwd):/app \
  scrapper-ent
```

### Option 2 : En local avec Python

#### 1. Créer un environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate  # sur macOS/Linux
# ou
venv\Scripts\activate  # sur Windows
```

#### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

#### 3. Passer les identifiants via variables d'environnement

```bash
export IDENTIFIANT="votre.email@viacesi.fr"
export MOT_DE_PASSE="votre_mot_de_passe"
python main.py
```

## Output

Le script génère un fichier `emploi_du_temps.ics` contenant tous les cours au format iCalendar, importable dans n'importe quel calendrier (Outlook, Google Calendar, etc.).

## Configuration

Les paramètres suivants peuvent être modifiés dans `main.py` :

- `NB_SEMAINES` : nombre de semaines à récupérer (par défaut : 4)
- `DELAI_ENTRE_SEMAINES_SECONDES` : délai entre chaque semaine durant le scraping (par défaut : 2)
- `TZ` : fuseau horaire (par défaut : Europe/Paris)

## Sécurité

⚠️ **Important** : Ne commitez jamais le fichier `.env` sur Git ! Il est déjà dans `.gitignore`.
