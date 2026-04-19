import { Play, Pause, SkipForward, SkipBack, Shuffle, Repeat } from 'lucide-react';

export function MediaScreen() {
  const upNext = [
    { title: 'Electric Dreams', artist: 'Midnight Radio', duration: '4:23' },
    { title: 'Sunset Drive', artist: 'Highway FM', duration: '3:54' },
    { title: 'City Lights', artist: 'Urban Beats', duration: '5:12' },
    { title: 'Night Cruise', artist: 'Drive FM', duration: '4:45' },
    { title: 'Summer Roads', artist: 'Coast Radio', duration: '3:38' },
  ];

  return (
    <div className="h-full pb-20 p-8 flex gap-8 bg-[#0a0a0a]">
      {/* Album Art - Left */}
      <div className="w-80 flex flex-col justify-center">
        <div className="aspect-square bg-gradient-to-br from-gray-800 to-gray-900 rounded-lg overflow-hidden border border-[#2a2a2a]">
          <div className="w-full h-full flex items-center justify-center">
            <div className="text-white/10 text-8xl">♪</div>
          </div>
        </div>
      </div>

      {/* Playback Controls - Center */}
      <div className="flex-1 flex flex-col justify-center px-8">
        <div className="mb-8">
          <div className="text-4xl text-white mb-2">Highway Nights</div>
          <div className="text-xl text-gray-400">Midnight Radio</div>
        </div>

        {/* Progress Bar */}
        <div className="mb-8">
          <div className="h-1 bg-[#2a2a2a] rounded-full overflow-hidden mb-2">
            <div className="h-full w-3/5 bg-white rounded-full" />
          </div>
          <div className="flex justify-between text-xs text-gray-500">
            <span>2:34</span>
            <span>4:12</span>
          </div>
        </div>

        {/* Control Buttons */}
        <div className="flex items-center justify-center gap-8">
          <button className="text-gray-400 hover:text-white transition-all">
            <Shuffle className="w-5 h-5" />
          </button>
          <button className="text-white hover:text-gray-300 transition-all">
            <SkipBack className="w-7 h-7" />
          </button>
          <button className="w-16 h-16 rounded-full bg-white hover:bg-gray-200 flex items-center justify-center transition-all">
            <Pause className="w-8 h-8 text-black" strokeWidth={2} />
          </button>
          <button className="text-white hover:text-gray-300 transition-all">
            <SkipForward className="w-7 h-7" />
          </button>
          <button className="text-gray-400 hover:text-white transition-all">
            <Repeat className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Up Next Queue - Right */}
      <div className="w-96 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-6">
        <div className="text-lg text-white mb-4">Up Next</div>
        <div className="space-y-2 overflow-y-auto max-h-[500px]">
          {upNext.map((track, index) => (
            <div
              key={index}
              className="bg-[#0a0a0a] hover:bg-[#2a2a2a] rounded-lg p-4 transition-all cursor-pointer"
            >
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 bg-[#2a2a2a] rounded flex items-center justify-center">
                  <Play className="w-4 h-4 text-gray-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-white text-sm truncate">{track.title}</div>
                  <div className="text-xs text-gray-500 truncate">{track.artist}</div>
                </div>
                <div className="text-xs text-gray-600">{track.duration}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
