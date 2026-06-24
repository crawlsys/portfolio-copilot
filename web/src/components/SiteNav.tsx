import Link from "next/link";
import { BriefcaseBusiness, Landmark, Newspaper } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SiteNav() {
  return (
    <nav className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm">
        <Link href="/">
          <BriefcaseBusiness className="h-4 w-4" />
          Portfolio
        </Link>
      </Button>
      <Button asChild variant="outline" size="sm">
        <Link href="/congressional">
          <Landmark className="h-4 w-4" />
          Congressional
        </Link>
      </Button>
      <Button asChild variant="outline" size="sm">
        <Link href="/digest">
          <Newspaper className="h-4 w-4" />
          Digest
        </Link>
      </Button>
    </nav>
  );
}
