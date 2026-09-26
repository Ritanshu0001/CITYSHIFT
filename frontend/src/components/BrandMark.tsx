import Link from "next/link";

type BrandMarkProps = {
  descriptor?: string;
};

export function BrandMark({ descriptor }: BrandMarkProps) {
  return (
    <Link
      href="/"
      className="brand-mark"
      aria-label={descriptor ? `CityShift — ${descriptor} home` : "CityShift home"}
    >
      <span className="brand-symbol" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="brand-word">CITYSHIFT</span>
      {descriptor && <span className="brand-descriptor">{descriptor}</span>}
    </Link>
  );
}
