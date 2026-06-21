import type { Request, Response, NextFunction } from "express";
import { config } from "../config.js";

export function authGuard(req: Request, res: Response, next: NextFunction): void {
  const key = req.get("apikey");
  if (!key || key !== config.apiKey) {
    res.status(401).json({ status: 401, error: "Unauthorized", response: { message: ["Invalid apikey"] } });
    return;
  }
  next();
}
