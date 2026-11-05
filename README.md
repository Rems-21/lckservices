# LCK Services SARL — Plateforme de Gestion du Transit & Groupage Maritime et Aérien

Application web centralisée développée sous **Python 3.11+ / Django 5.x**, **Bootstrap 5.3** et **MySQL (InnoDB)** permettant de piloter l'ensemble des opérations de transit et de groupage maritime et aérien de **LCK Services SARL** (Version 1.0).

---

## 1. Architecture & Technologies

- **Backend** : Python 3.11+, Django 5.1, Django ORM
- **Base de données** : MySQL / MariaDB (moteur transactionnel **InnoDB**, `utf8mb4`), configurée via `.env`
- **Frontend** : HTML5, CSS3, JavaScript ES6, Bootstrap 5.3, Chart.js, SweetAlert2
- **Génération documentaire** : WeasyPrint (factures, reçus, manifestes, bons de livraison, étiquettes et rapports PDF avec bascule automatique sur `xhtml2pdf` sous Windows si GTK3 n'est pas installé), OpenPyXL (exports Excel `.xlsx` multi-feuilles), `qrcode` (QR Codes de vérification d'authenticité)
- **Devise** : **FCFA** en devise principale de comptabilisation et de facturation, avec conversion multi-devises (`FCFA`, `USD`, `EUR`, `CNY`) sur les dépenses de transit et les valeurs déclarées

---

## 2. Démarrage Rapide

```powershell
# 1. Activer l'environnement virtuel
.\.venv\Scripts\Activate.ps1

# 2. Appliquer les migrations sur MySQL (base lck_services_db)
python manage.py migrate

# 3. Initialiser les référentiels, le compte administrateur et les données de démonstration
python manage.py init_lck --with-demo

# 4. Lancer le serveur de développement
python manage.py runserver
```

Accédez ensuite à [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

---

## 3. Comptes Utilisateurs Préconfigurés

Conformément au cahier des charges, tous les utilisateurs authentifiés disposent du rôle fonctionnel unique **Utilisateur** et accèdent à tous les modules métiers :

| Identifiant | Mot de passe | Spécificité |
| :--- | :--- | :--- |
| `admin` | `LckAdmin2026!` | Compte administrateur initial (gestion et création des autres comptes utilisateurs) |
| `agent` | `LckAgent2026!` | Compte utilisateur opérationnel |

---

## 4. Exécution des Tests Automatisés

```powershell
.\.venv\Scripts\python.exe manage.py test
```
