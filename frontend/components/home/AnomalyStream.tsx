/** The flagged-observation feed.
 *
 * These are real detections, not a shell for a feed that might exist later:
 * every ingestion re-scores its series against a median/MAD Z-score and a Tukey
 * fence, and 25,413 observations currently carry a flag. The endpoint returns
 * them **most severe first**, so that is what the header says — a feed labelled
 * "latest" that is actually sorted by magnitude is the kind of small lie this
 * product cannot afford.
 *
 * Severity is carried three ways at once, because colour alone is never
 * allowed to carry it: the badge names the direction in words, the Z-score is
 * printed, and a dot pulses only above |z| = 3. The pulses are offset from each
 * other so they never beat in unison, which is the difference between a signal
 * and a decoration.
 */

import { RevealGroup, RevealItem } from '@/components/motion/Reveal';
import { AnomalyBadge, Empty, Meta, SectionHead } from '@/components/primitives';
import { formatValue, indicatorTitle, type AnomalyRecord } from '@/lib/api';

export function AnomalyStream({
  anomalies,
  total,
}: {
  anomalies: AnomalyRecord[];
  total: number | null;
}) {
  return (
    <section aria-labelledby="flagged-heading">
      <SectionHead
        title={<span id="flagged-heading">Flagged observations</span>}
        meta={
          <Meta>
            most severe first, one reading per series
            {total !== null && <> · {total.toLocaleString('en-US')} held</>}
          </Meta>
        }
      />

      {anomalies.length === 0 ? (
        <Empty
          title="Nothing flagged yet"
          hint="Every series is re-scored after the ingestion that touches it. A reading is flagged when it breaks both a median-based Z-score and its window's interquartile fence."
        />
      ) : (
        <RevealGroup className="mt-3" step={0.035}>
          {anomalies.map((anomaly, index) => (
            <RevealItem key={`${anomaly.country_code}-${anomaly.indicator_code}-${anomaly.date}`}>
              <FlaggedRow anomaly={anomaly} index={index} />
            </RevealItem>
          ))}
        </RevealGroup>
      )}
    </section>
  );
}

function FlaggedRow({ anomaly, index }: { anomaly: AnomalyRecord; index: number }) {
  const severe = anomaly.z_score !== null && Math.abs(anomaly.z_score) >= 3;

  return (
    <a
      href={`/country/${anomaly.country_code}?indicator=${encodeURIComponent(anomaly.indicator_code)}`}
      className="group grid grid-cols-[auto_1fr_auto] items-start gap-x-3 border-t border-[color:var(--hairline)] py-2.5 transition-colors duration-200 first:border-t-0 hover:bg-[color:var(--plane-2)]/70"
    >
      <span className="relative mt-[7px] flex size-1.5 items-center justify-center">
        {severe && (
          <span
            aria-hidden
            className="absolute size-1.5 rounded-full bg-alert"
            style={{
              animation: 'alert-pulse 2.8s var(--ease-in-out) infinite',
              animationDelay: `${(index % 5) * 0.45}s`,
            }}
          />
        )}
        <span
          aria-hidden
          className="size-1.5 rounded-full"
          style={{ background: severe ? 'var(--alert)' : 'var(--alert-soft)', opacity: severe ? 1 : 0.55 }}
        />
      </span>

      <span className="min-w-0">
        <span className="block truncate text-[13px] text-ink transition-colors duration-200 group-hover:text-signal">
          {anomaly.country_name ?? anomaly.country_code}
        </span>
        <span className="mt-0.5 block truncate">
          <Meta>
            {indicatorTitle(anomaly.indicator_name) || anomaly.indicator_code} · {anomaly.date.slice(0, 7)}
          </Meta>
        </span>
      </span>

      <span className="flex flex-col items-end gap-1">
        <span data-numeric className="text-[13px] text-ink">
          {formatValue(anomaly.value)}
        </span>
        <AnomalyBadge deviationType={anomaly.deviation_type} zScore={anomaly.z_score} />
      </span>
    </a>
  );
}
