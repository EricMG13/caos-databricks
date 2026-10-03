// D94: a quote the module cited on one page and the host found, as one whole
// evidence line, on another is anchored where it is. The page shown is the
// true one; this says which page the module named.
export function Reanchored({ cited, found }: { cited: number | null | undefined; found: number }) {
  if (cited === null || cited === undefined) return null;
  return (
    <div className="note" data-reanchored>
      Cited p.{cited}, found p.{found}: the module named page {cited}; the host found this line on
      page {found} and anchored it there.
    </div>
  );
}
