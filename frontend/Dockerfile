# First stage: build the app
FROM node:latest

# Set working directory
WORKDIR /opt/app

# Copy package files first to leverage Docker layer caching
COPY package*.json ./

# Install dependencies
RUN npm install next.js

# Copy the rest of the source code
COPY . .

# Start the app
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
