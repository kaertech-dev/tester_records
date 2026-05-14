# Tester Records — Test Traceability System

## Purpose
This project is a web-based system for managing tester records and traceability in a manufacturing or engineering environment. It allows users to log, track, and close transactions related to test equipment, fixtures, and personnel, ensuring data integrity and easy access to historical records.

## Features
- **Create New Transactions:** Log new tester records with product, model, station, classification, and fixture details.
- **Close Transactions:** Review and close open transactions, recording actions taken and responsible personnel.
- **Download Data:** Export tester records as CSV files by day, week, month, or custom range.
- **User Authentication:** Secure actions with group/badge authentication for person-in-charge.
- **Modern UI:** Responsive, user-friendly interface with clear workflows.

## Tech Stack
- **Backend:** Python, Flask, SQLAlchemy, PyMySQL
- **Frontend:** HTML, CSS (custom, responsive), JavaScript
- **Database:** MySQL (two databases: `te` and `projectsdb`)
- **Containerization:** Docker, Docker Compose

## Project Structure
```
app.py                  # Main Flask app
backend/                # Backend logic (DB, queries, blueprints)
static/                 # CSS, JS, images
templates/              # HTML templates
requirements.txt        # Python dependencies
Dockerfile, docker-compose.yaml
.env (not committed)    # Environment variables
```

## Setup & Usage
1. **Clone the repository:**
   ```sh
   git clone https://github.com/kaertech-dev/tester_records.git
   cd tester_records
   ```
2. **Configure environment:**
   - Copy `.env.example` to `.env` and fill in DB credentials.
3. **Build and run with Docker Compose:**
   ```sh
   docker-compose up --build
   ```
   The app will be available at `http://localhost:5000`.
4. **Manual (local) run:**
   - Install Python 3.11+
   - Install dependencies: `pip install -r requirements.txt`
   - Run: `python app.py`

## Security Notes
- **Never commit `.env` or sensitive credentials.**
- For production, set a persistent `SECRET_KEY` and use secure DB credentials.

## Contributing
Pull requests and issues are welcome! Please add tests and update documentation as needed.

## License
[MIT License](LICENSE)
