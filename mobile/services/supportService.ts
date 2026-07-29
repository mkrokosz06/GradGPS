import api from "./api";

/**
 * Send a support message. The backend forwards it to the support inbox via
 * SES — the destination address never lives in the app bundle.
 */
export async function sendSupportMessage(
  email: string,
  subject: string,
  message: string,
): Promise<void> {
  await api.post("/support/contact", { email, subject, message });
}
