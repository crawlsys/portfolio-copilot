export type AccountOption = {
  id: string;
  label: string;
};

const DEFAULT_ACCOUNTS: AccountOption[] = [
  { id: "5424-5456", label: "Schwab One Joint" },
  
];

export function getAccountOptions(): AccountOption[] {
  const configured = process.env.NEXT_PUBLIC_ACCOUNT_IDS;
  if (!configured) {
    return DEFAULT_ACCOUNTS;
  }

  const accounts = configured
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      const [id, label] = entry.split(":").map((part) => part.trim());
      return {
        id,
        label: label || id,
      };
    })
    .filter((account) => account.id);

  return accounts.length > 0 ? accounts : DEFAULT_ACCOUNTS;
}
