import { Select } from "./Select";

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"));

/* Выбор времени «ЧЧ:ММ» в стиле мини-аппа — два кастомных дропдауна вместо
   нативного <input type="time"> (его колёсико-пикер рисует сама ОС/браузер
   и никак не темизируется под тёмную/светлую тему приложения). */
export function TimeField({
  value,
  onChange,
  className = "",
}: {
  value: string; // "HH:MM" или "HH:MM:SS"
  onChange: (v: string) => void; // отдаёт "HH:MM"
  className?: string;
}) {
  const [hh, mm] = value.split(":");
  const h = HOURS.includes(hh) ? hh : "00";
  const m = MINUTES.includes(mm) ? mm : "00";

  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      <Select
        value={h}
        onChange={(v) => onChange(`${v}:${m}`)}
        options={HOURS.map((o) => ({ value: o, label: o }))}
        className="flex-1"
      />
      <span className="shrink-0 text-[16px] font-semibold text-text-tertiary" aria-hidden>
        :
      </span>
      <Select
        value={m}
        onChange={(v) => onChange(`${h}:${v}`)}
        options={MINUTES.map((o) => ({ value: o, label: o }))}
        className="flex-1"
      />
    </div>
  );
}
