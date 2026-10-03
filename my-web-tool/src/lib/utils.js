export function formatMessageTime(date = new Date()) {
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function cn(...classes) {
  return classes.filter(Boolean).join(" ");
}
