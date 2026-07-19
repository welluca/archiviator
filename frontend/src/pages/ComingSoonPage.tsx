import { Construction } from 'lucide-react';

interface ComingSoonPageProps {
  title: string;
}

export default function ComingSoonPage({ title }: ComingSoonPageProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <Construction className="w-12 h-12 text-space-500 mb-4" />
      <h1 className="text-xl font-semibold text-white mb-1">{title}</h1>
      <p className="text-gray-500 text-sm">Coming soon — this section is planned for a later milestone.</p>
    </div>
  );
}
