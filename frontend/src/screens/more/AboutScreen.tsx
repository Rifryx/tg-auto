import { useNavigate } from "react-router-dom";
import { BackHeader } from "./PersonasScreen";

export function AboutScreen() {
  const navigate = useNavigate();
  return (
    <div className="pb-6 pt-1">
      <BackHeader title="О приложении" onBack={() => navigate("/more")} />
      <div className="card p-5">
        <p className="text-[17px] font-semibold text-text-primary">Neuro-Commenting</p>
        <p className="mt-1 text-[13px] text-text-secondary">Версия 0.1.0</p>
        <p className="mt-4 text-[14px] leading-relaxed text-text-secondary">
          Панель управления Telegram-аккаунтами: прогрев, пул и модуль
          комментирования. Работает как Telegram Mini App.
        </p>
      </div>
    </div>
  );
}
