import { StudentSignIn } from "./student-sign-in";

export const metadata = { title: "Student sign-in | Rantau" };

export default async function StudentSignInPage({ searchParams }: {
  searchParams: Promise<{ next?: string }>;
}) {
  const next = (await searchParams).next;
  // The return destination is a fixed product route, never an arbitrary URL.
  return <StudentSignIn destination={next === "payments" ? "/student/payments" : "/student/chat"} />;
}
