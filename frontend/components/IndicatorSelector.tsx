'use client';

import { useRouter, useSearchParams } from 'next/navigation';

import { sourceLabel, type IndicatorOption } from '@/lib/api';

interface Props {
  options: IndicatorOption[];
  selected: string;
}

export function IndicatorSelector({ options, selected }: Props) {
  const router = useRouter();
  const params = useSearchParams();

  const onChange = (code: string) => {
    const next = new URLSearchParams(params.toString());
    next.set('indicator', code);
    router.push(`/?${next.toString()}`);
  };

  return (
    <label className="flex items-center gap-2 text-sm">
      <span style={{ color: 'var(--text-secondary)' }} className="whitespace-nowrap">
        Indicator
      </span>
      <select
        value={selected}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 max-w-[26rem] flex-1 truncate rounded-md border px-3 py-1.5 text-sm"
        style={{
          background: 'var(--bg-elevated)',
          borderColor: 'var(--border)',
          color: 'var(--text-primary)',
        }}
      >
        {options.map((o) => (
          <option key={`${o.source}:${o.indicator_code}`} value={o.indicator_code}>
            {o.indicator_name} · {sourceLabel(o.source)} ({o.country_count})
          </option>
        ))}
      </select>
    </label>
  );
}
