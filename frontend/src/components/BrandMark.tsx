import Link from "next/link";

export function BrandMark() {
  return (
    <Link href="/" className="brand-mark" aria-label="CityShift home">
      <span className="brand-symbol" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="brand-word">CITYSHIFT</span>
    </Link>
  );
}
