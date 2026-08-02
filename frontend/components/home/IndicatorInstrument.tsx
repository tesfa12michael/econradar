'use client';

/** The indicator control.
 *
 * A `<select>` was hiding the most interesting fact in the database. There are
 * 23 series across 14 concepts, and three of them measure unemployment in ways
 * that are not interchangeable — an ILO-modelled estimate harmonised across 187
 * countries, national definitions from 118, and a monthly US series. Picking
 * between them blind is exactly the metric confusion decision #36 exists to
 * prevent, and a dropdown listing 23 names in a row makes it unavoidable.
 *
 * So the control groups by concept, marks which series is primary for each, and
 * shows every one's coverage and measurement basis in the list. Choosing is
 * informed rather than lucky.
 */

import { CaretUpDown, Check } from '@phosphor-icons/react/dist/ssr';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { Meta } from '@/components/primitives';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  basisSummary,
  conceptLabel,
  indicatorTitle,
  sourceLabel,
  yearOf,
  type IndicatorMetadata,
} from '@/lib/api';
import { cn } from '@/lib/utils';

interface Props {
  catalogue: IndicatorMetadata[];
  selected: string;
  /** Falls back to the catalogue entry; passed separately because the map
   * response is authoritative for what is actually plotted. */
  selectedName: string | null;
}

export function IndicatorInstrument({ catalogue, selected, selectedName }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const current = catalogue.find((m) => m.indicator_code === selected);

  /* Grouped by concept, primary series first inside each group, and the groups
   * themselves ordered by how much of the world they cover — so the list opens
   * on the series that fill the map rather than the ones with four countries. */
  const groups = useMemo(() => {
    const byConcept = new Map<string, IndicatorMetadata[]>();
    for (const meta of catalogue) {
      const key = meta.concept ?? 'other';
      const bucket = byConcept.get(key);
      if (bucket) bucket.push(meta);
      else byConcept.set(key, [meta]);
    }
    return [...byConcept.entries()]
      .map(([concept, series]) => ({
        concept,
        series: [...series].sort(
          (a, b) =>
            Number(b.is_primary_for_concept) - Number(a.is_primary_for_concept) ||
            (b.country_count ?? 0) - (a.country_count ?? 0),
        ),
      }))
      .sort(
        (a, b) => (b.series[0].country_count ?? 0) - (a.series[0].country_count ?? 0),
      );
  }, [catalogue]);

  const choose = (code: string) => {
    setOpen(false);
    router.push(`/?indicator=${encodeURIComponent(code)}`, { scroll: false });
  };

  const basis = current ? basisSummary(current) : [];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Change indicator"
          className={cn(
            'group block max-w-[36rem] rounded-md px-2 py-1.5 text-left -mx-2',
            'transition-colors duration-200 hover:bg-[color:var(--plane-2)]/60',
          )}
        >
          {/* Sized to its own length. These are the agencies' official series
              names, which run from "Exports" to "Unemployment, total (% of
              total labor force) (modeled ILO estimate)" — one display size for
              both gives a title that is either timid or three lines deep, and
              the name cannot be shortened without misrepresenting which series
              is on screen. */}
          <span
            className={cn(
              'block font-medium leading-[1.08] tracking-[-0.025em] text-ink',
              displaySize(indicatorTitle(selectedName ?? current?.indicator_name) || selected),
            )}
          >
            {indicatorTitle(selectedName ?? current?.indicator_name) || selected}
          </span>

          {/* Coverage on one line, measurement basis on the next. Run together
              they wrap mid-phrase and orphan a word, and the two answer
              different questions anyway: how much of the world is in this
              series, and what exactly it counts. */}
          {current && (
            <>
              <span className="mt-2.5 block">
                <Meta className="text-ink-muted">
                  {current.country_count} countries · {yearOf(current.earliest_date)}-
                  {yearOf(current.latest_date)} · {sourceLabel(current.source)}
                </Meta>
              </span>
              {basis.length > 0 && (
                <span className="mt-0.5 block">
                  <Meta>{basis.join(' · ')}</Meta>
                </span>
              )}
            </>
          )}

          {/* The affordance says how many other series there are, which is the
              fact that makes it worth opening. */}
          <span className="mt-3 inline-flex items-center gap-1.5 text-[12px] text-ink-dim transition-colors duration-200 group-hover:text-signal">
            <CaretUpDown aria-hidden weight="bold" className="size-3.5" />
            <span data-numeric>{catalogue.length} series</span>
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={10}
        className="w-[min(30rem,calc(100vw-2rem))] border-[color:var(--edge)] bg-[color:var(--plane-glass)] p-0 backdrop-blur-xl"
      >
        <Command
          className="bg-transparent"
          filter={(value, search) =>
            value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0
          }
        >
          <CommandInput
            placeholder={`Search ${catalogue.length} series…`}
            className="text-[13px] placeholder:text-ink-dim"
          />
          <CommandList className="max-h-[24rem]">
            <CommandEmpty className="px-3 py-6 text-[13px] text-ink-dim">
              No series matches that.
            </CommandEmpty>
            {groups.map(({ concept, series }) => (
              <CommandGroup
                key={concept}
                heading={
                  <span className="text-[11px] font-medium text-ink-muted">
                    {conceptLabel(concept)}
                  </span>
                }
                className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-3"
              >
                {series.map((meta) => (
                  <SeriesRow
                    key={meta.indicator_code}
                    meta={meta}
                    active={meta.indicator_code === selected}
                    onSelect={() => choose(meta.indicator_code)}
                  />
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function displaySize(name: string): string {
  if (name.length <= 28) return 'text-[clamp(1.7rem,3.4vw,2.6rem)]';
  if (name.length <= 46) return 'text-[clamp(1.5rem,3vw,2.25rem)]';
  return 'text-[clamp(1.3rem,2.3vw,1.75rem)]';
}

function SeriesRow({
  meta,
  active,
  onSelect,
}: {
  meta: IndicatorMetadata;
  active: boolean;
  onSelect: () => void;
}) {
  const basis = basisSummary(meta);
  return (
    <CommandItem
      value={`${meta.indicator_name} ${meta.indicator_code} ${meta.concept ?? ''} ${sourceLabel(meta.source)}`}
      onSelect={onSelect}
      className="items-start gap-2.5 rounded-md px-3 py-2 data-[selected=true]:bg-[color:var(--plane-3)]"
    >
      <Check
        aria-hidden
        weight="bold"
        className={cn('mt-0.5 size-3.5 shrink-0 text-signal', !active && 'opacity-0')}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-[13px] text-ink">{indicatorTitle(meta.indicator_name)}</span>
          {meta.is_primary_for_concept && (
            <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.12em] text-signal-dim">
              primary
            </span>
          )}
        </span>
        <span className="mt-1 block">
          <Meta>
            {meta.country_count} countries · {yearOf(meta.earliest_date)}-
            {yearOf(meta.latest_date)} · {sourceLabel(meta.source)}
            {basis.length > 0 && <> · {basis.join(' · ')}</>}
          </Meta>
        </span>
      </span>
    </CommandItem>
  );
}
