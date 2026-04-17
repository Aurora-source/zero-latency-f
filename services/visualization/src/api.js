import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function withRetry(requestFn, retries = 8, delayMs = 2500) {
  let lastError;

  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      return await requestFn();
    } catch (error) {
      lastError = error;
      if (attempt === retries) {
        throw error;
      }
      await sleep(delayMs);
    }
  }

  throw lastError;
}

export async function fetchSegments(city) {
  return withRetry(async () => {
    const response = await api.get(`/segments/${city}`);
    return response.data;
  });
}

export async function fetchRoute(payload) {
  return withRetry(async () => {
    const response = await api.post("/route", payload);
    return response.data;
  });
}
