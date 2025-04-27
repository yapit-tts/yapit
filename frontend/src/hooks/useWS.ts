import useWebSocket, { Options } from 'react-use-websocket';

const WS_URL = "ws://localhost:8000";

export const useWS = (
  path = "",
  options: Options = {}
) => {
  const fullUrl = `${WS_URL}${path}`;
  return useWebSocket(fullUrl, {
    share: true,
    shouldReconnect: () => true,
		binaryType: 'arraybuffer',
    ...options,
  });
};
