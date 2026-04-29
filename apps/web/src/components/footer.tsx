export function Footer() {
  return (
    <footer className="border-t mt-auto px-6 py-4 text-xs text-muted-foreground">
      <div className="max-w-6xl mx-auto flex flex-wrap items-center justify-between gap-3">
        <div>RAG Platform — Pipeline-as-a-Service для документов</div>
        <nav className="flex items-center gap-4">
          <a href="/pricing" className="hover:text-foreground">Тарифы</a>
          <a href="/terms" className="hover:text-foreground">Оферта</a>
          <a href="/privacy" className="hover:text-foreground">Конфиденциальность</a>
          <a href="/delivery" className="hover:text-foreground">Доставка</a>
          <a href="/contacts" className="hover:text-foreground">Контакты</a>
        </nav>
      </div>
    </footer>
  );
}
