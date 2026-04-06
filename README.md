# Smart Fleet Monitoring System

A backend system that monitors vehicles in real-time, processes sensor data, and generates alerts based on rule-based decision logic.

## Features

- Add and manage vehicles via REST API
- Receive and store real-time sensor data (temperature, status)
- Automatic alert generation when thresholds are exceeded
- Simple dashboard to visualize vehicle status and alerts
- Data simulation script for testing

## Tech Stack

- Python, FastAPI, SQLite, SQLAlchemy, Streamlit

## Project Structure
smart-fleet/
├── main.py          # API endpoints
├── models.py        # Database models
├── database.py      # Database connection
├── app.py           # Streamlit dashboard
└── simulate_data.py # Fake data simulator

## Setup
```bash
git clone https://github.com/Ilsuyuksel133/smart-fleet.git
cd smart-fleet
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn sqlalchemy streamlit requests
```

## Run

Start the API:
```bash
uvicorn main:app --reload
```

Start the dashboard:
```bash
streamlit run app.py
```

Run simulation:
```bash
python simulate_data.py
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /vehicles | Add a new vehicle |
| POST | /vehicles/{id}/data | Send sensor data |
| GET | /vehicles | List all vehicles |
| GET | /vehicles/{id}/status | Get vehicle status |
| GET | /alerts | List all alerts |

## Alert Logic

- Temperature > 80°C → generates high temperature alert
- Status != "OK" → generates abnormal status alert

## Screenshots

*(Add screenshots of Streamlit dashboard here)*
