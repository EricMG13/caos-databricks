// Admin, /admin/. It has no section document: the one thing it holds is the
// rate deck, which the card reads and saves for itself. The workspace mounts
// this view directly rather than through `RegionState`, and every other
// section keeps the document path.
import { RateDeckCard } from "./RateDeckCard";

export function AdminSection(_props: { document?: undefined; tab?: string | null }) {
  return <RateDeckCard />;
}
