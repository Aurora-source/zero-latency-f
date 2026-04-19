import { Phone, PhoneCall, PhoneMissed, PhoneIncoming } from 'lucide-react';

export function PhoneScreen() {
  const recentCalls = [
    { name: 'Sarah Johnson', type: 'outgoing', time: '10 min ago', avatar: 'SJ' },
    { name: 'Mike Chen', type: 'incoming', time: '1 hour ago', avatar: 'MC' },
    { name: 'Emily Davis', type: 'missed', time: '2 hours ago', avatar: 'ED' },
    { name: 'Alex Turner', type: 'incoming', time: '3 hours ago', avatar: 'AT' },
    { name: 'Jessica Park', type: 'outgoing', time: 'Yesterday', avatar: 'JP' },
    { name: 'David Lee', type: 'incoming', time: 'Yesterday', avatar: 'DL' },
  ];

  const favorites = [
    { name: 'Home', avatar: 'H' },
    { name: 'Office', avatar: 'O' },
    { name: 'Mom', avatar: 'M' },
    { name: 'Dad', avatar: 'D' },
  ];

  const getCallIcon = (type: string) => {
    switch (type) {
      case 'outgoing': return <PhoneCall className="w-4 h-4 text-blue-500" />;
      case 'incoming': return <PhoneIncoming className="w-4 h-4 text-green-500" />;
      case 'missed': return <PhoneMissed className="w-4 h-4 text-red-500" />;
      default: return <Phone className="w-4 h-4" />;
    }
  };

  return (
    <div className="h-full pb-20 p-8 flex gap-6 bg-[#0a0a0a]">
      {/* Favorites - Left */}
      <div className="w-80 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-6">
        <div className="text-lg text-white mb-4">Favorites</div>
        <div className="grid grid-cols-2 gap-3">
          {favorites.map((contact, index) => (
            <button
              key={index}
              className="bg-[#0a0a0a] hover:bg-[#2a2a2a] rounded-lg p-5 transition-all flex flex-col items-center gap-3"
            >
              <div className="w-16 h-16 bg-[#2a2a2a] rounded-full flex items-center justify-center text-xl text-white">
                {contact.avatar}
              </div>
              <span className="text-sm text-white">{contact.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Recent Calls - Center/Right */}
      <div className="flex-1 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-8">
        <div className="flex items-center justify-between mb-6">
          <div className="text-xl text-white">Recent Calls</div>
          <button className="w-14 h-14 bg-green-500 hover:bg-green-400 rounded-full flex items-center justify-center transition-all">
            <Phone className="w-6 h-6 text-black" />
          </button>
        </div>

        <div className="space-y-2">
          {recentCalls.map((call, index) => (
            <div
              key={index}
              className="bg-[#0a0a0a] hover:bg-[#2a2a2a] rounded-lg p-5 transition-all flex items-center gap-5 cursor-pointer"
            >
              <div className="w-12 h-12 bg-[#2a2a2a] rounded-full flex items-center justify-center text-sm text-white">
                {call.avatar}
              </div>
              <div className="flex-1">
                <div className="text-white mb-1">{call.name}</div>
                <div className="text-xs text-gray-500">{call.time}</div>
              </div>
              <div className="flex items-center gap-4">
                {getCallIcon(call.type)}
                <button className="w-10 h-10 bg-[#2a2a2a] hover:bg-[#3a3a3a] rounded-full flex items-center justify-center transition-all">
                  <Phone className="w-4 h-4 text-green-500" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
