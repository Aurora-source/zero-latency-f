FROM node:20-alpine

WORKDIR /app

COPY package.json .
RUN npm install

COPY index.html ./index.html
COPY vite.config.js ./vite.config.js
COPY src ./src

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
