import type { NextPageContext } from "next";

interface ErrorProps {
  statusCode?: number;
}

function ErrorPage({ statusCode }: ErrorProps) {
  return (
    <div style={{ padding: "2rem", maxWidth: "640px", margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.875rem", fontWeight: 700 }}>
        {statusCode ?? "Error"}
      </h1>
      <p>Something went wrong.</p>
    </div>
  );
}

ErrorPage.getInitialProps = ({ res, err }: NextPageContext) => {
  const statusCode = res?.statusCode ?? err?.statusCode ?? 404;
  return { statusCode };
};

export default ErrorPage;
