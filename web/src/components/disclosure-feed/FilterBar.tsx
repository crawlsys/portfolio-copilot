"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type CongressionalFilters = {
  member: string;
  symbol: string;
  since: string;
  chamber: string;
  sort: string;
};

type FilterBarProps = {
  filters: CongressionalFilters;
};

export function FilterBar({ filters }: FilterBarProps) {
  const router = useRouter();
  const [member, setMember] = useState(filters.member);
  const [symbol, setSymbol] = useState(filters.symbol);
  const [since, setSince] = useState(filters.since);
  const [chamber, setChamber] = useState(filters.chamber || "all");
  const [sort, setSort] = useState(filters.sort || "disclosure_date");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    setParam(params, "member", member);
    setParam(params, "symbol", symbol.toUpperCase());
    setParam(params, "since", since);
    setParam(params, "chamber", chamber === "all" ? "" : chamber);
    setParam(params, "sort", sort === "disclosure_date" ? "" : sort);
    router.push(`/congressional${params.size ? `?${params.toString()}` : ""}`);
  }

  function reset() {
    setMember("");
    setSymbol("");
    setSince("");
    setChamber("all");
    setSort("disclosure_date");
    router.push("/congressional");
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-md border border-border bg-card p-4"
    >
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_160px_170px_150px_190px_auto] lg:items-end">
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-normal text-muted-foreground">
            Member
          </span>
          <Input
            value={member}
            onChange={(event) => setMember(event.target.value)}
            placeholder="Search member"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-normal text-muted-foreground">
            Symbol
          </span>
          <Input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
            placeholder="AAPL"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-normal text-muted-foreground">
            Since
          </span>
          <Input
            type="date"
            value={since}
            onChange={(event) => setSince(event.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-normal text-muted-foreground">
            Chamber
          </span>
          <Select value={chamber} onValueChange={setChamber}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="house">House</SelectItem>
              <SelectItem value="senate">Senate</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-normal text-muted-foreground">
            Sort
          </span>
          <Select value={sort} onValueChange={setSort}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="disclosure_date">Disclosure date</SelectItem>
              <SelectItem value="transaction_date">Transaction date</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <div className="flex gap-2">
          <Button type="submit" className="min-w-24">
            <Search className="h-4 w-4" />
            Apply
          </Button>
          <Button type="button" variant="outline" size="icon" onClick={reset}>
            <X className="h-4 w-4" />
            <span className="sr-only">Reset filters</span>
          </Button>
        </div>
      </div>
    </form>
  );
}

function setParam(params: URLSearchParams, key: string, value: string) {
  const cleaned = value.trim();
  if (cleaned) {
    params.set(key, cleaned);
  }
}
