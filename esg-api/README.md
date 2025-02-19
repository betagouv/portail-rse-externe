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
  - Redis
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

### List of end-points

| Method | Endpoint            | Description                |
|--------|---------------------|----------------------------|
| POST   | `/ping`             | Check API health status    |
| POST   | `/upload`           | Upload PDF                 |
| POST   | `/pdf2txt`          | Convert PDF to texts       |
| GET    | `/gettxtfile`       | Get texts (CSV file)       |
| POST   | `/esrspredict`      | Predict ESRS from text     |
| GET    | `/checkactivetask`  | Check if a task is active  |
| GET    | `/getnbactivetasks` | Check active task number   |
| GET    | `/getpredsfile`     | Get ESRS predictions (CSV  |
| POST   | `/clean`            | Clean temporary files      |

### Explanations of prediction calls
When calling **/esrspredict**, the API returns **{'status': {'code': 0, 'msg': 'Task started'}}** immediately but the task will run in the background.
To find out if the task is still running, call **/checkactivetask** with a **pdf_key**.
If it returns **{'nb_tasks': '0' ..}**, the task is finished and you can get the prediction file using **getpredsfile**. At any time, you can call **getnbactivetasks** to get the number of background tasks. If this number is greater than **NB_PARALLEL_TASKS_IN_API (in api.py)**, **/esrspredict** will return **{'status': {'code': -3, 'msg': 'Too many task : 2 task running'}}** message and you will have to wait for the number of tasks to decrease and retry your prediction call to the API later.

---

## 📜 License
This project is licensed under the AGPL License – see the LICENSE file for details.

---

## 📧 Contact
Author: François Bullier  
Email: fbullier@360client.fr