import { describe, expect, it } from "vitest";
import {
  authorsShort,
  catalogLabel,
  knowledgeBanner,
  sourceMeta,
  sourcesLabel,
} from "@/lib/sources";
import type { Source } from "@/lib/types";

const paper: Source = {
  id: "1",
  url: "https://doi.org/10.1/x",
  title: "P",
  kind: "scholarly",
  authors: ["A", "B", "C", "D"],
  year: 2017,
  venue: "NeurIPS",
  doi: "10.1/x",
  citation_count: 90000,
};

describe("sourcesLabel", () => {
  it("names every combination", () => {
    expect(sourcesLabel(true, true)).toBe("Web + Scholarly");
    expect(sourcesLabel(true, false)).toBe("Web");
    expect(sourcesLabel(false, true)).toBe("Scholarly");
    expect(sourcesLabel(false, false)).toBe("None");
  });
});

describe("catalogLabel", () => {
  it("maps known ids and echoes unknown ones", () => {
    expect(catalogLabel("openalex")).toBe("OpenAlex");
    expect(catalogLabel("semantic_scholar")).toBe("Semantic Scholar");
    expect(catalogLabel("arxiv")).toBe("arXiv");
    expect(catalogLabel("pubmed")).toBe("PubMed");
    expect(catalogLabel("zenodo")).toBe("zenodo");
  });
});

describe("authorsShort / sourceMeta", () => {
  it("truncates to three authors with et al.", () => {
    expect(authorsShort(["A", "B"])).toBe("A, B");
    expect(authorsShort(["A", "B", "C", "D"])).toBe("A, B, C et al.");
    expect(authorsShort(undefined)).toBe("");
  });
  it("renders the full meta line", () => {
    expect(sourceMeta(paper)).toBe("A, B, C et al. (2017) · NeurIPS · 90,000 citations");
  });
  it("omits missing parts and returns null for web sources", () => {
    expect(sourceMeta({ ...paper, authors: [], year: undefined, citation_count: undefined })).toBe("NeurIPS");
    expect(sourceMeta({ ...paper, authors: undefined, year: undefined, venue: undefined, citation_count: undefined })).toBeNull();
    expect(sourceMeta({ id: "2", url: "https://a.com", title: "A" })).toBeNull();
  });
});

describe("knowledgeBanner", () => {
  it("only fires when web search is off", () => {
    expect(knowledgeBanner(true, true)).toBeNull();
    expect(knowledgeBanner(undefined, undefined)).toBeNull();
    expect(knowledgeBanner(false, false)).toBe("offline");
    expect(knowledgeBanner(false, undefined)).toBe("offline");
    expect(knowledgeBanner(false, true)).toBe("scholarly-only");
  });
});
