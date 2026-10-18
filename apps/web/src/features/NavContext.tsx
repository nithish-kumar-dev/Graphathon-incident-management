import { createContext, useContext } from "react";
import type { TabId } from "./types";

/** Lets any component link to another workspace section without prop drilling. */
const NavContext = createContext<(tab: TabId) => void>(() => undefined);

export const NavProvider = NavContext.Provider;

export function useNavigateTab(): (tab: TabId) => void {
  return useContext(NavContext);
}
