function [NPV1] = System(Cap)
%% Overall ESS File
% This function calculates the NPV of an ESS for frequency response using
% the capacity of 2 ESSs as inputs. 
%clear 
%clc
%Cap = [5 0.00];

% NOTE: When decribing power it is relative to the ESS. This means the a
% -ve power is a ESS charging and a +ve power is it discharging





%% Nomenclature



% Frequency data is loaded into workspace
load('Frequency.mat')

% Define size of output arrays
P_Required = zeros(1,length(Fr));
P_output1 = zeros(1,length(Fr));
P_output2 = zeros(1,length(Fr));
SOC1 = zeros(1,length(Fr)); SOC10 = zeros(1,length(Fr));
SOC2 = zeros(1,length(Fr)); SOC20 = zeros(1,length(Fr));

SOH = 1;
if Cap(2) == 0
    c = 0;
else 
    c = 1;
end
% A for loop is created for each second of frequency data
gamma_d = 1; SOC10(1) = 0.5; SOC20(1) = c*0.5;
    % The required power is calculated from the Power Function
    

for i = 1:length(Fr)
    P_Required(i) = PowerFreq(Fr(i));
  % The control function is implemented 
  [P_output1(i), P_output2(i),SOC1(i),SOC2(i),b] = Control(P_Required(i), SOC10(i), SOC20(i), Cap, gamma_d(end));
  SOC10(i+1) = SOC1(i);
  P_output1(i+1) = P_output1(i);
  SOC20(i+1) = c*SOC2(i); 
  P_output2(i+1) = c*P_output2(i);
  P_Out(i) = (P_output1(i)*b(1) + P_output2(i)*b(2))'; 
  
  % The degradation is calculated each month
  if mod(i,2628000)==0 % This determines a month interval
      n = (i/2628000);
      [L_cyc, L_cal] = cycle_count(SOC1(1:i),[1:i]);
      L = L_cal + sum(L_cyc); 
      SOH(n) = 1 - L;
      gamma_d(n) = SOH(n);
  end
  if SOH(end) < 0.8
      break
  end
  
end

%%
x = [1:i]/86400; Life = round((0.2/(L)),0);
LM  = (round((0.2/(L/12)),0) - (Life*12));
% The power not delivered is calculated
P_Missed = (abs(P_Required(1:i)) - abs(P_Out));
P_Missed = P_Missed';

% The missed power and required power are converted into a matrix where
% each column represents one month
P_Missed_Month = reshape(P_Missed,2628000,n);
P_Required_Month = reshape(P_Required(1:i),2628000,n);
% Set NPV function inputs.
PPP = sum(P_Missed_Month);
TTT = sum(abs(P_Required_Month));
PP = repmat(PPP,1,Life);
TT = repmat(TTT,1,Life);
if LM > 0
    NPV_In.P_Missed = [PP,PP(1:LM)];
    NPV_In.P_Required = [TT,TT(1:LM)];
elseif LM == 0
    NPV_In.P_Missed = PP;
    NPV_In.P_Required = TT;
elseif LM < 0
    yy = length(PP) + LM;
    PP(yy:end) = [];
    TT(yy:end) = [];
    NPV_In.P_Missed = PP;
    NPV_In.P_Required = TT;
end
    



NPV_In.Cap1 = Cap(1);
NPV_In.Cap2 = Cap(2);

% Call NPV function
[NPV_Out] = NPV(NPV_In,c);
NPV1 = -NPV_Out.NPV;
%NPV_Aim = NPV_Out.NPV;
%plot(NPV_Out.Month,NPV_Out.Cash,'-')
end
