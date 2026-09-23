import type { ReactNode } from "react";

/* Главная кнопка flow-экрана.
   Телефон: липкая панель у нижнего края (палец рядом, навбар на flow скрыт).
   Десктоп: обычная строка в конце формы, кнопка справа и не во всю ширину. */
export function StickyActionBar({ children }: { children: ReactNode }) {
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-30 mx-auto max-w-[440px] border-t border-hairline bg-bg-base px-5 pt-3 pb-[calc(env(safe-area-inset-bottom)+12px)] lg:static lg:mx-0 lg:mt-8 lg:flex lg:max-w-none lg:justify-end lg:border-0 lg:bg-transparent lg:p-0 lg:[&>*]:w-auto lg:[&>*]:min-w-[260px]"
    >
      {children}
    </div>
  );
}
