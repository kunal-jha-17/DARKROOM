import { redirect } from "next/navigation";

// "/" is normally served by the rewrite in next.config.mjs; this is the fallback.
export default function Home() {
  redirect("/darkroom.html");
}
