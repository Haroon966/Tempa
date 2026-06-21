/** Normalize phone number to WhatsApp JID. */
export function createJid(number: string): string {
  if (number.includes("@")) return number;
  let clean = number.replace(/[^\d+]/g, "");
  if (clean.startsWith("+")) clean = clean.slice(1);
  const isGroup = clean.includes("-");
  return `${clean}@${isGroup ? "g.us" : "s.whatsapp.net"}`;
}
