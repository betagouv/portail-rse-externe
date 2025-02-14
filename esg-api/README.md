# 🚀 ESG-API

A RESTful API for handling ESG (Environmental, Social, and Governance) data. Built with Flask and Nginx, deployed using Docker and Docker Compose.

---

## 📖 Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Docker Support](#docker-support)
- [API Endpoints](#api-endpoints)
- [License](#license)
- [Contact](#contact)

---

## 📌 Introduction

The **ESG-API** extracts text from PDF files and identifies relevant content related to ESRS (European Sustainability Reporting Standards). It allows users to upload PDFs, extract text, and generate ESG-related predictions.

Designed for scalability, this API leverages:
- **Flask** as the backend framework
- **Nginx** as a reverse proxy
- **Docker Compose** for containerized deployment

---

## ✨ Features

- ✅ **Secure PDF Upload**
- ✅ **Text Extraction from PDFs**
- ✅ **ESRS Predictions from Text**
- ✅ **Containerized Deployment with Docker**
- ✅ **Scalability with uWSGI and Nginx**

---

## ⚙️ Installation

### Prerequisites
Installation is designed for an **AlmaLinux 9 server** and requires:
  - Docker
  - Docker-compose
  - Nginx
  - Python 3.11
  - UWSGI
  - Flask

### Clone the Repository
```sh
sudo dnf install git -y
git clone https://github.com/your-username/esg-api.git
cd esg-api
```

### Installation script
```sh
chmod +x setup-alma9.sh
./setup-alma9.sh
```

### API alive test
```sh
curl --insecure https://YOUR_SERVER_NAME/ping
```

---

## 🐳 Docker Support

### Run API with Docker Compose
```sh
sudo docker-compose up -d --build
```
### Stop Containers
```sh
sudo docker-compose up -d
```

### Rebuild Containers (Force No Cache)
```sh
sudo docker-compose up -d --build
```

### Check Docker-compose logs
```sh
sudo docker-compose logs nginx
```

### Check Flask container logs
```sh
sudo docker logs esg-api-flask-1
```

### Check uWSGI processes
```sh
sudo docker exec -it esg-api-flask-1 bash
uwsgitop /tmp/uwsgi-stats.sock
```

---

## 🔗 API Endpoints

| Method | Endpoint        | Description                |
|--------|-----------------|----------------------------|
| POST   | `/ping`         | Check API health status    |
| POST   | `/upload`       | Upload PDF                 |
| POST   | `/pdf2txt`      | Convert PDF to texts       |
| GET    | `/gettxtfile`   | Get texts (CSV file)              |
| POST   | `/esrspredict`  | Predict ESRS from text     |
| GET    | `/getpredsfile` | Get ESRS predictions (CSV File)       |
| POST   | `/clean`        | Clean temporary files      |

---

## 📜 License
This project is licensed under the AGPL License – see the LICENSE file for details.

---

## 📧 Contact
Author: François Bullier  
Email: fbullier@360client.fr