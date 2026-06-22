"use server";

import { revalidatePath } from "next/cache";
import { refreshPortfolio } from "@/api/client";

export async function refreshPortfolioAction(accountId: string) {
  const result = await refreshPortfolio(accountId);
  revalidatePath("/");
  revalidatePath(`/portfolio/${accountId}`);
  return result;
}
