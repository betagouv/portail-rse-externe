FROM nginx:latest

# Copy the nginx configuration file
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Ensure the directories exist
RUN mkdir -p /etc/ssl/certs /etc/ssl/private

# Copy SSL certificates and key
COPY certs/nginx-selfsigned.crt /etc/ssl/certs/nginx-selfsigned.crt
COPY certs/nginx-selfsigned.key /etc/ssl/private/nginx-selfsigned.key

