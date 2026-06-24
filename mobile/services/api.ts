import axios from "axios";
import { API_BASE } from "../constants/api";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

export default api;
