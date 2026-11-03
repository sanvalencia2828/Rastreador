import LoginForm from "./LoginForm";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ expired?: string; next?: string }>;
}) {
  const { expired, next } = await searchParams;
  return <LoginForm expired={expired === "1"} next={next ?? null} />;
}
