FROM python:3.11-slim

ENV TZ=Europe/Paris

# Installer les dépendances système pour Chrome et Selenium
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier requirements.txt et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le script principal
COPY main.py .

# Les identifiants doivent être passés via variables d'environnement
# Exemple: docker run -e IDENTIFIANT=... -e MOT_DE_PASSE=... scrapper-ent

# Commande par défaut
CMD ["python", "main.py"]
