// Host-only reads: what the settings drawer needs to offer choices.

export interface QuestionCategory {
  id: string;
  count: number;
}

export async function fetchCategories(): Promise<QuestionCategory[]> {
  const response = await fetch("/api/categories", { credentials: "same-origin" });
  if (!response.ok) throw new Error("Couldn't load the question categories.");
  return response.json();
}
