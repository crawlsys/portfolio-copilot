"use client";

import { useRouter } from "next/navigation";
import type { AccountOption } from "@/lib/accounts";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type AccountSelectorProps = {
  accounts: AccountOption[];
  selectedAccountId: string;
};

export function AccountSelector({
  accounts,
  selectedAccountId,
}: AccountSelectorProps) {
  const router = useRouter();

  return (
    <div className="w-full sm:w-64">
      <Select
        value={selectedAccountId}
        onValueChange={(accountId) => router.push(`/portfolio/${accountId}`)}
      >
        <SelectTrigger aria-label="Select account">
          <SelectValue placeholder="Select account" />
        </SelectTrigger>
        <SelectContent>
          {accounts.map((account) => (
            <SelectItem key={account.id} value={account.id}>
              {account.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
