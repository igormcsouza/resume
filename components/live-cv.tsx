"use client";

import { useEffect, useState } from "react";

import CvView from "@/components/cv-view";
import type { Cv, Lang } from "@/lib/cv";
import { fetchSnapshot } from "@/lib/snapshot";

/** Renders the bundled CV (static, works offline and for print), then swaps in the live snapshot if it loads. */
export default function LiveCv({ lang, initial }: { lang: Lang; initial: Cv }) {
  const [cv, setCv] = useState(initial);
  useEffect(() => {
    fetchSnapshot().then((live) => live && setCv(live));
  }, []);
  return <CvView lang={lang} cv={cv} />;
}
