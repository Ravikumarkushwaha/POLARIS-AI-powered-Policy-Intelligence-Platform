import { useEffect, useState } from "react";
export function useDisplayPreference() {
  const [detail, setDetail] = useState(false);
  useEffect(() => {
    try {
      setDetail(localStorage.getItem("polaris-display") === "detail");
    } catch {
      /* optional */
    }
  }, []);
  const change = (value: boolean) => {
    setDetail(value);
    try {
      localStorage.setItem("polaris-display", value ? "detail" : "summary");
    } catch {
      /* optional */
    }
  };
  return [detail, change] as const;
}
