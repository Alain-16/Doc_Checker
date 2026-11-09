"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Crumb = { label: string; href?: string };

const CrumbContext = createContext<{ crumbs: Crumb[] | null; set: (c: Crumb[] | null) => void }>({
  crumbs: null,
  set: () => {},
});

export function CrumbProvider({ children }: { children: React.ReactNode }) {
  const [crumbs, set] = useState<Crumb[] | null>(null);
  return <CrumbContext.Provider value={{ crumbs, set }}>{children}</CrumbContext.Provider>;
}

export function useCrumbState() {
  return useContext(CrumbContext).crumbs;
}

/** A page declares its breadcrumb trail: `useCrumbs([{label:"Vendors", href:"/vendors"}, {label: name}])`. */
export function useCrumbs(crumbs: Crumb[]) {
  const { set } = useContext(CrumbContext);
  const key = JSON.stringify(crumbs);
  useEffect(() => {
    set(JSON.parse(key));
    return () => set(null);
  }, [key, set]);
}
