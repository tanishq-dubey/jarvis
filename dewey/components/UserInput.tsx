import React from 'react';

interface UserInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
}

const UserInput: React.FC<UserInputProps> = ({ value, onChange, onSend }) => {
  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="p-4 bg-gray-800">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyPress={handleKeyPress}
        className="w-full p-2 bg-gray-700 text-white rounded-lg resize-none"
        rows={3}
        placeholder="Type your message here..."
      />
      <button
        onClick={onSend}
        className="mt-2 px-4 py-2 bg-blue-600 text-white rounded-lg"
      >
        Send
      </button>
    </div>
  );
};

export default UserInput;