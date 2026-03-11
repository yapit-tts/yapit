import { createContext } from "react";
import type { InlineContent } from "./structuredDocument";

// Map from footnote label to paragraph ASTs (pre-extracted for lightweight context)
export const FootnoteContext = createContext<ReadonlyMap<string, InlineContent[][]>>(new Map());
