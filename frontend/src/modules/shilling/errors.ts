/* Перевод кодов ошибок отправки (execution_log.error) на русский.
 *
 * Логика вынесена в общий shared/tgError (её переиспользуют логи комментинга и
 * аккаунта). Здесь — обратно совместимый реэкспорт под старым именем. */

export { humanizeTgError as humanizeShillingError } from "../../shared/tgError";
