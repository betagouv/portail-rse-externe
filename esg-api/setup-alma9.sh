#!/bin/bash

# Function to check for errors
check_error() {
  if [ $? -ne 0 ]; then
    echo "Error encountered. Exiting."
    exit 1
  fi
}

# Update du système 
sudo dnf update -y
check_error

## Install the EPEL repository package
sudo dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
sudo dnf repolist
check_error

#  Installer iptables
sudo dnf install iptables-services -y
check_error

sudo systemctl enable iptables
sudo systemctl start iptables
check_error

sudo systemctl status iptables
sudo iptables -L
check_error

# Set iptables rules for secure traffic
echo "Setting iptables rules..."

# Reset existing rules
sudo iptables -F
sudo iptables -X
sudo iptables -Z
sudo iptables -P INPUT ACCEPT
sudo iptables -P FORWARD ACCEPT
sudo iptables -P OUTPUT ACCEPT

# Apply api rules
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
check_error

sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
check_error

sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
check_error

sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
check_error

sudo iptables -A INPUT -i lo -j ACCEPT
check_error

sudo iptables -A OUTPUT -o lo -j ACCEPT
check_error

sudo iptables -P INPUT DROP
check_error

# Add Docker rule
sudo iptables -N DOCKER
sudo iptables -t filter -I FORWARD -o docker0 -j DOCKER
sudo iptables -N DOCKER-ISOLATION-STAGE-1
sudo iptables -t filter -I FORWARD -j DOCKER-ISOLATION-STAGE-1

# Create the directory for iptables rules if it doesn't exist
echo "Ensuring /etc/iptables directory exists..."
sudo mkdir -p /etc/iptables
check_error

# Save the iptables rules
echo "Saving iptables rules..."
sudo iptables-save | sudo tee /etc/iptables/rules.v4
check_error

# todo : Persisting rules when rebooting

# Install perl for nginx routing
sudo dnf install -y pcre pcre-devel
check_error

# Install required packages for Docker if not already installed
echo "Installing required packages for Docker..."
sudo dnf install -y dnf-utils device-mapper-persistent-data lvm2
check_error

# Add Docker's official repository if not already added
if ! sudo dnf repolist | grep -q "docker-ce-stable"; then
  echo "Adding Docker's official repository..."
  sudo dnf config-manager --add-repo=https://download.docker.com/linux/centos/docker-ce.repo
  check_error
else
  echo "Docker repository already added."
fi

# Install Docker if not already installed
if ! command -v docker &> /dev/null; then
  echo "Installing Docker..."
  sudo dnf install -y docker-ce docker-ce-cli containerd.io
  check_error
else
  echo "Docker already installed."
fi

# Start and enable Docker if not already running
if ! sudo systemctl is-active --quiet docker; then
  echo "Starting and enabling Docker..."
  sudo systemctl start docker
  sudo systemctl enable docker
  check_error
else
  echo "Docker already running."
fi

# Install Docker Compose if not already installed
if ! command -v docker-compose &> /dev/null; then
  echo "Installing Docker Compose..."
  latest_version=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -Po '"tag_name": "\K.*\d')
  sudo curl -L "https://github.com/docker/compose/releases/download/${latest_version}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  check_error
  sudo chmod +x /usr/local/bin/docker-compose
  sudo rm -f /usr/bin/docker-compose  
  sudo ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose
  check_error
else
  echo "Docker Compose already installed."
fi

# Create directories for SSL certificates if they don't exist
mkdir -p nginx/certs
sudo mkdir -p /etc/ssl/private
sudo mkdir -p /etc/ssl/certs

# Check if certificates already exist
if [ -f nginx/certs/nginx-selfsigned.crt ] && [ -f nginx/certs/nginx-selfsigned.key ]; then
  echo "SSL certificates already exist. Skipping generation."

else
  # Generate self-signed SSL certificates
  echo "Generating self-signed SSL certificates..."
  sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout nginx/certs/nginx-selfsigned.key -out nginx/certs/nginx-selfsigned.crt <<EOF
US
State
City
Organization
Unit
localhost
email@example.com
EOF

  # Permission to copy certifcates
  sudo chmod -R 755 nginx/certs
  sudo chmod 644 nginx/certs/nginx-selfsigned.crt
  sudo chmod 600 nginx/certs/nginx-selfsigned.key

  # Copy certificates to /etc/ssl
  echo "Copying certificates to /etc/ssl..."
  cp nginx/certs/nginx-selfsigned.key /etc/ssl/private/nginx-selfsigned.key
  cp nginx/certs/nginx-selfsigned.crt /etc/ssl/certs/nginx-selfsigned.crt

fi

# Create Docker volume for model storage if not already created
if ! docker volume inspect model_volume &> /dev/null; then
  echo "Creating Docker volume for model storage..."
  sudo docker volume create model_volume
  check_error
else
  echo "Docker volume already created."
fi

# Build and start Docker containers using Docker Compose
echo "Building and starting Docker containers using Docker Compose..."
sudo /usr/local/bin/docker-compose up --build -d
check_error

echo "Setup completed successfully!"
