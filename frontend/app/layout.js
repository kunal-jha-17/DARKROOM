export const metadata = {
  title: "Darkroom",
  description: "Dark patterns caught on live Indian checkouts, with evidence",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
